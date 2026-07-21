# DataPond Frontend

Next.js operator UI for the **Portable AI Data Foundation**.

## Product information architecture

| Area | Routes | Visibility |
|---|---|---|
| Home | `/dashboard` | Core |
| Build AI | `/knowledge`, `/ai` | Core |
| Data | `/connectors`, `/catalog`, `/query` | Adapter capability-gated |
| Add-ons | `/pipelines`, `/streaming`, `/dashboards`, `/notebooks`, `/experiments` | Add-on capability-gated |
| Operate | `/governance`, `/storage`, `/services`, `/system`, `/settings` | Core |
| Learn | `/docs`, `/help` | Core |

The shell displays the runtime deployment profile returned by `/api/capabilities`. Profile metadata is descriptive; boolean capability flags determine feature visibility.

## UX rules

1. Knowledge and AI Gateway are the primary product journey.
2. Optional navigation fails closed until the backend explicitly returns `true`.
3. Direct access to a disabled route explains the missing adapter/add-on and links to profile guidance.
4. Disabled OSS components are not described as automatically replaced by cloud services.
5. Service health and capability state remain separate.
6. Existing URLs stay stable across profiles.

## Key files

- `components/app-sidebar.tsx` — navigation information architecture
- `lib/capabilities.tsx` — capability provider and direct-route state
- `lib/product-profile.ts` — profile/adapters presentation
- `components/dashboard/journey-strip.tsx` — capability-aware core workflow
- `app/docs/` — in-app product documentation
- `app/help/` — workflow guides

Canonical product documentation lives in the repository root `README.md` and `docs/`.

## Development

```bash
npm install
npm run dev
```

Open <http://localhost:3000>. The backend is expected behind `/api`; see `next.config.ts` and `proxy.ts` for routing behavior.

## Validation

```bash
npx tsc --noEmit
npm run lint
npm run build
```

The repository currently carries a broader lint backlog; changed files should not add new errors. Production builds must pass.

## Next.js version note

This project uses Next.js 16. Read the local rules in `AGENTS.md` and the installed Next.js documentation before changing framework APIs or routing conventions.
