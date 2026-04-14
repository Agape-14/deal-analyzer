import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Dashboard skeleton. Mirrors the real layout so the page doesn't jump when
 * content resolves. Shimmer is short-running; if this shows for more than a
 * second the real data is probably in trouble.
 */
export default function DashboardLoading() {
  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-12">
      <div className="mb-8">
        <Skeleton className="h-3 w-20 mb-2" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-4 w-96 mt-3" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4 mb-10">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} elevated className="p-5 space-y-3">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-20" />
            <Skeleton className="h-3 w-24" />
          </Card>
        ))}
      </div>

      <div className="mb-6 flex items-center gap-3">
        <Skeleton className="h-9 flex-1 max-w-md" />
        <Skeleton className="h-9 w-80" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} elevated className="p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 space-y-2">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
              <Skeleton className="h-12 w-12 rounded-full" />
            </div>
            <div className="grid grid-cols-3 gap-3 pt-2">
              {Array.from({ length: 3 }).map((__, j) => (
                <div key={j} className="space-y-1.5">
                  <Skeleton className="h-2.5 w-12" />
                  <Skeleton className="h-4 w-16" />
                </div>
              ))}
            </div>
            <Skeleton className="h-4 w-20" />
          </Card>
        ))}
      </div>
    </div>
  );
}
