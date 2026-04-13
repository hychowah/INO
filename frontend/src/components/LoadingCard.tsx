import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

type LoadingCardProps = {
  label: string;
  rows?: number;
};

export function LoadingCard({ label, rows = 3 }: LoadingCardProps) {
  return (
    <Card>
      <CardContent className="space-y-4 py-6">
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-28" />
        </div>
        <div className="space-y-3">
          {Array.from({ length: rows }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
        <p className="text-sm text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  );
}