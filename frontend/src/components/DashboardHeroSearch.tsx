type SearchScope = 'all' | 'plenary' | 'committee' | 'speech' | 'appendix';

export interface DashboardHeroSearchProps {
  selectedScope: SearchScope;
  onScopeChange: (scope: SearchScope) => void;
  query: string;
  onQueryChange: (value: string) => void;
}

const SEARCH_SCOPES: { id: SearchScope; label: string; placeholder: string }[] = [
  { id: 'all', label: '전체', placeholder: '예: GTX 착공' },
  { id: 'plenary', label: '본회의', placeholder: '예: 본회의 GTX 착공 관련 질의' },
  { id: 'committee', label: '상임위', placeholder: '예: 건설교통위원회 GTX 착공' },
  { id: 'speech', label: '의원 발언', placeholder: '예: 김경기도 의원 5분발언' },
  { id: 'appendix', label: '부록·자료', placeholder: '예: GTX 착공 부록 자료' },
];

export default function DashboardHeroSearch({
  selectedScope,
  onScopeChange,
  query,
  onQueryChange,
}: DashboardHeroSearchProps) {
  const activeScope = SEARCH_SCOPES.find((scope) => scope.id === selectedScope) ?? SEARCH_SCOPES[0];

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5 sm:p-6" aria-label="통합 검색 영역">
      <h2 className="text-lg sm:text-xl font-semibold text-gray-900">의회 맥락 통합 검색</h2>
      <p className="mt-2 text-sm text-gray-600">회의 유형과 발언 맥락을 탭으로 빠르게 좁혀 검색해보세요.</p>

      <div role="tablist" aria-label="검색 범위" className="mt-4 flex flex-wrap gap-2">
        {SEARCH_SCOPES.map((scope) => {
          const isActive = scope.id === selectedScope;
          return (
            <button
              key={scope.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={`search-panel-${scope.id}`}
              id={`search-tab-${scope.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onScopeChange(scope.id)}
              className={`px-3 py-1.5 rounded-full border text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
                isActive
                  ? 'bg-primary text-white border-primary'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
              }`}
            >
              {scope.label}
            </button>
          );
        })}
      </div>

      <div
        className="mt-4"
        role="tabpanel"
        id={`search-panel-${activeScope?.id}`}
        aria-labelledby={`search-tab-${activeScope?.id}`}
      >
        <label htmlFor="dashboard-search" className="sr-only">
          의회 통합 검색 입력
        </label>
        <input
          id="dashboard-search"
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={activeScope?.placeholder}
          className="w-full rounded-md border border-gray-300 px-4 py-3 text-sm sm:text-base text-gray-900 placeholder:text-gray-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          aria-describedby="dashboard-search-help"
        />
        <p id="dashboard-search-help" className="mt-2 text-xs sm:text-sm text-gray-500">
          예시 질의: GTX 착공 · 김경기도 의원 5분발언
        </p>
      </div>
    </section>
  );
}

export { SEARCH_SCOPES };
export type { SearchScope };
