"use client"

/** A choice among a few options, as a row of toggle buttons with radio semantics.
 *  The console used native selects for three-way choices (PII mode, schedule,
 *  expiry), which hide the alternatives behind a click. */
export function ChoiceGroup<T>({ label, options, value, onChange, disabled }: {
  label: string
  options: { label: string; value: T; disabled?: boolean; title?: string }[]
  value: T
  onChange: (v: T) => void
  disabled?: boolean
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map(o => {
        const on = o.value === value
        return (
          <button key={o.label} type="button" role="radio" aria-checked={on} title={o.title}
                  disabled={disabled || o.disabled} onClick={() => onChange(o.value)}
                  className={`h-8 rounded-md border px-3 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${on
                    ? "border-primary bg-primary/10 font-semibold text-primary"
                    : "bg-card hover:border-primary/50"}`}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
