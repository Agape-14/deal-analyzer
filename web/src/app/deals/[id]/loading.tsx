import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function DealDetailLoading() {
  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <Skeleton className="h-3 w-20 mb-4" />
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
        <div className="flex-1 space-y-3">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-4 w-64" />
          <div className="grid grid-cols-4 gap-6 pt-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-6 w-20" />
              </div>
            ))}
          </div>
        </div>
        <Skeleton className="h-32 w-32 rounded-full" />
      </div>

      <Skeleton className="mt-10 h-10 w-96" />

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-6">
        <Card elevated className="p-6 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </Card>
        <Card elevated className="p-6 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </Card>
      </div>
    </div>
  );
}
