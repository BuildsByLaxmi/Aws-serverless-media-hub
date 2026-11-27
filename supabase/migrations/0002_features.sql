-- Run in Supabase Dashboard > SQL Editor AFTER 0001_security.sql. Non-destructive, safe to re-run.
-- Adds optional columns for: before/after report (dimensions), image quality score (PSNR),
-- and the per-file settings chosen by the intelligent output selection.
alter table public.media_metadata add column if not exists original_width integer;
alter table public.media_metadata add column if not exists original_height integer;
alter table public.media_metadata add column if not exists optimized_width integer;
alter table public.media_metadata add column if not exists optimized_height integer;
alter table public.media_metadata add column if not exists psnr_db numeric(5,2);
alter table public.media_metadata add column if not exists settings_used jsonb;
-- service_role already has table-level privileges from 0001; re-grant to be safe for new columns.
grant select, insert, update, delete on public.media_metadata to service_role;
