import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function PortfolioLoading() {
  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-8 md:py-10">
      <div className="mb-8 space-y-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-4 w-80" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} elevated className="p-5 space-y-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-7 w-28" />
            <Skeleton className="h-3 w-24" />
          </Card>
        ))}
      </div>

      <Card elevated className="mt-8 p-6 space-y-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-[280px] w-full" />
      </Card>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-6">
        <Card elevated className="p-6 space-y-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-[180px] w-[180px] rounded-full mx-auto" />
        </Card>
        <Card elevated className="p-6 space-y-4">
          <Skeleton className="h-4 w-24" />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </Card>
      </div>
    </div>
  );
}
