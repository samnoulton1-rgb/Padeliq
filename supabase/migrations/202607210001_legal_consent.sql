alter table public.profiles
  add column if not exists legal_consent_version text,
  add column if not exists legal_consented_at timestamptz;

comment on column public.profiles.legal_consent_version is
  'Version of the Terms and Privacy Policy explicitly accepted by the account holder.';
comment on column public.profiles.legal_consented_at is
  'Timestamp of explicit Terms and Privacy Policy consent.';
