update public.matches
set position_score = null
where analysis_result is null and position_score is not null;

alter table public.matches
  drop constraint if exists matches_position_score_requires_analysis;

alter table public.matches
  add constraint matches_position_score_requires_analysis
  check (position_score is null or analysis_result is not null);

comment on constraint matches_position_score_requires_analysis on public.matches
  is 'Position scores may only be stored when a video analysis result is present.';
