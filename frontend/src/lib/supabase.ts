/**
 * Supabase 클라이언트 설정
 */

import { createClient } from "@supabase/supabase-js";

import type { SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/**
 * 환경변수 검증 함수
 * 런타임에 환경변수가 설정되었는지 확인합니다.
 */
function validateEnvVariables(): void {
  if (!supabaseUrl) {
    throw new Error("Missing environment variable: NEXT_PUBLIC_SUPABASE_URL");
  }
  if (!supabaseAnonKey) {
    throw new Error("Missing environment variable: NEXT_PUBLIC_SUPABASE_ANON_KEY");
  }
}

/**
 * Supabase 클라이언트 인스턴스 (lazy initialization)
 */
let supabaseInstance: SupabaseClient | null = null;

/**
 * Supabase 클라이언트를 가져옵니다.
 * 클라이언트 사이드에서 사용하는 공개(anon) 키 기반 클라이언트
 */
export function getSupabaseClient(): SupabaseClient {
  if (!supabaseInstance) {
    validateEnvVariables();
    supabaseInstance = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    });
  }
  return supabaseInstance;
}

/**
 * Supabase 클라이언트를 생성하는 팩토리 함수
 * 서버 컴포넌트나 특수한 설정이 필요한 경우 사용
 */
export function createSupabaseClient(
  url: string = supabaseUrl,
  key: string = supabaseAnonKey
): SupabaseClient {
  if (!url || !key) {
    throw new Error("Supabase URL and Key are required");
  }
  return createClient(url, key, {
    auth: {
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: true,
    },
  });
}

/**
 * 기본 Supabase 클라이언트 (편의를 위한 export)
 * 주의: 빌드 시에는 환경변수가 없을 수 있으므로 getSupabaseClient() 사용 권장
 */
export const supabase = supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null;

export default getSupabaseClient;
