import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-xl bg-slate-800/50 border border-slate-700/50", className)}
      {...props}
    />
  )
}

export { Skeleton }
