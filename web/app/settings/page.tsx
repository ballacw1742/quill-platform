import { redirect } from "next/navigation";

/**
 * /settings — settings currently live on the Profile screen; this route
 * exists so the home-screen avatar menu's "Settings" item resolves
 * (UI_REDESIGN_BRIEF §3). A dedicated settings screen is a Phase 4 concern.
 */
export default function SettingsPage() {
  redirect("/profile");
}
