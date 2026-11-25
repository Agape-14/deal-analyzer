// Leave room below Cloudflare's 100 MB request limit for multipart framing.
const MAX_BATCH_BYTES = 90_000_000;

type IntakeIssue = {
  file_index?: number;
  filename?: string;
  detail?: string;
};

type IntakeReply = {
  deal_id: number;
  documents: unknown[];
  errors: IntakeIssue[];
  detail?: string;
};

function* intakeBatches(files: readonly File[]): Generator<File[]> {
  let batch: File[] = [];
  let batchBytes = 0;
  for (const file of files) {
    if (batch.length && batchBytes + file.size > MAX_BATCH_BYTES) {
      yield batch;
      batch = [];
      batchBytes = 0;
    }
    batch.push(file);
    batchBytes += file.size;
  }
  if (batch.length) yield batch;
}

function failedFiles(batch: File[], errors: IntakeIssue[]): File[] {
  const failed = new Set<number>();
  for (const { file_index, filename } of errors) {
    if (typeof file_index === "number" && Number.isInteger(file_index) && file_index >= 0 && file_index < batch.length) {
      failed.add(file_index);
      continue;
    }
    // During rollout, an older API may still send errors without an index.
    // Keep all possible matches and let the API deduplicate them on retry.
    const matches = batch.flatMap((file, index) => file.name === filename ? [index] : []);
    if (!matches.length) return batch;
    for (const index of matches) failed.add(index);
  }
  return batch.filter((_, index) => failed.has(index));
}

export async function uploadDealDocuments(
  files: readonly File[],
  intakeToken: string,
  projectName: string,
  dealId: number | null,
): Promise<{ dealId: number | null; remainingFiles: File[]; error: string | null }> {
  let confirmed = 0;
  for (const batch of intakeBatches(files)) {
    const body = new FormData();
    body.append("intake_token", intakeToken);
    body.append("project_name", projectName);
    for (const file of batch) body.append("files", file);

    // Keep an unconfirmed batch on network or proxy errors. The API may have
    // saved it before the connection failed and can deduplicate it on retry.
    const response = await fetch("/document-upload/intake", { method: "POST", body }).catch(() => null);
    const reply: IntakeReply | null = await response?.json().catch(() => null) ?? null;
    const remainingFiles = files.slice(confirmed);
    if (!response?.ok) {
      if (typeof reply?.detail === "string") return { dealId, remainingFiles, error: reply.detail };
      const error = response?.status === 413
        ? "This upload exceeds the connection’s size limit. Try fewer or smaller documents at a time."
        : "Upload was interrupted. Retry the selected documents.";
      return { dealId, remainingFiles, error };
    }
    if (!reply || !Number.isSafeInteger(reply.deal_id) || reply.deal_id <= 0 ||
        (dealId !== null && reply.deal_id !== dealId) || !Array.isArray(reply.documents) ||
        !Array.isArray(reply.errors) || reply.documents.length + reply.errors.length !== batch.length ||
        reply.errors.some(issue => !issue || typeof issue !== "object")) {
      return { dealId, remainingFiles, error: "The server did not confirm the upload. If your session expired, sign in and retry." };
    }

    dealId = reply.deal_id;
    confirmed += batch.length;
    if (reply.errors.length) {
      return {
        dealId,
        remainingFiles: [...failedFiles(batch, reply.errors), ...files.slice(confirmed)],
        error: reply.errors.map(issue => `${issue.filename ?? "Document"}: ${issue.detail ?? "Could not save this file"}`).join(" · "),
      };
    }
  }
  return { dealId, remainingFiles: [], error: null };
}
