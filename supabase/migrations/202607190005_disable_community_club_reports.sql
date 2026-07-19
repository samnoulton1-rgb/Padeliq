-- The club directory is curated from public venue sources. Community reports
-- are retained for audit/history, but no client may add or alter them.
drop policy if exists users_insert_own_club_reports on public.club_reports;
drop policy if exists users_update_own_club_reports on public.club_reports;
drop policy if exists users_delete_own_club_reports on public.club_reports;

revoke insert, update, delete on public.club_reports from anon, authenticated;

