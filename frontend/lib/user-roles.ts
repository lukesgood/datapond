/** Presentation logic for Settings → Users → role picker.
 *
 *  `app/permissions.py` defines seven roles and `PATCH /auth/users/{id}` already
 *  accepts all of them (backend/app/api/auth.py `update_user`). This module only
 *  turns what `GET /api/me/permissions` served — `assignable_roles`, an array of
 *  `{name, label, permissions}` (see lib/permissions.tsx `AssignableRole`) — into
 *  options a `<Select>` can render.
 *
 *  It holds no role descriptions of its own. `label` is the one sentence
 *  `backend/app/permissions.py` `ROLE_LABELS` wrote for that role; a second, English
 *  copy here is exactly the kind of copy that goes stale the next time the matrix
 *  changes. `roleOptions` only formats what the server sent, and falls back to the
 *  bare role name when a label is missing — a role the client doesn't recognise
 *  still has to render, not disappear, or an admin looking at a user with that role
 *  would see an empty picker.
 *
 *  There is no `nextRoleAfterToggle`. That made sense when the product had exactly
 *  two roles (admin/viewer) and "the other one" was a well-defined answer; with
 *  seven roles, toggling to "the next one" isn't a question an admin ever means to
 *  ask, so the settings page offers a `<Select>` on every row instead of a button
 *  that cycles roles.
 */

/** What `assignable_roles` in a GET /api/me/permissions response carries per role.
 *  `label` and `permissions` are optional here (not in lib/permissions.tsx's stricter
 *  `AssignableRole`) so this function stays honest about the one case it exists to
 *  handle: a role the server sent that this build doesn't otherwise know about. */
export interface RoleSource {
  name: string
  label?: string
  permissions?: string[]
}

export interface RoleOption {
  value: string
  /** The server's sentence for this role, or the bare name when none was sent. */
  label: string
  /** One line, separate from `label`: how many permissions the role holds and a
   *  few of them by name, so "data_scientist" and "ai_engineer" read as different
   *  answers rather than two words. Falls back to `label` for a role with no
   *  permissions data at all, so it is never empty. */
  description: string
}

const MAX_HEADLINE_PERMISSIONS = 3

export function roleOptions(assignable: RoleSource[]): RoleOption[] {
  return assignable.map((role) => {
    const label = role.label && role.label.trim() ? role.label : role.name
    const permissions = role.permissions ?? []
    const headline = permissions.slice(0, MAX_HEADLINE_PERMISSIONS)
    const remainder = permissions.length - headline.length

    const description = permissions.length
      ? `${permissions.length} permission${permissions.length === 1 ? "" : "s"}: ` +
        `${headline.join(", ")}${remainder > 0 ? `, +${remainder} more` : ""}`
      : label

    return { value: role.name, label, description }
  })
}
