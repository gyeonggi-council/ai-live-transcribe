-- Migration 008: Create collaborative editing tables
-- Run this in Supabase Dashboard SQL Editor

CREATE TABLE IF NOT EXISTS edit_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL REFERENCES meetings(id),
  editor_name VARCHAR(100) NOT NULL,
  status VARCHAR(20) DEFAULT 'active',
  started_at TIMESTAMPTZ DEFAULT now(),
  last_active_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subtitle_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subtitle_id UUID NOT NULL REFERENCES subtitles(id),
  meeting_id UUID NOT NULL REFERENCES meetings(id),
  author_name VARCHAR(100) NOT NULL,
  content TEXT NOT NULL,
  resolved BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
