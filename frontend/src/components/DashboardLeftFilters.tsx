interface FilterSectionProps {
  title: string;
  items: string[];
}

function FilterSection({ title, items }: FilterSectionProps) {
  return (
    <section className="rounded-md border border-gray-100 bg-gray-50 p-3" aria-label={`${title} 필터`}>
      <h4 className="text-sm font-semibold text-gray-900">{title}</h4>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <button
            key={item}
            type="button"
            className="rounded-full border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            {item}
          </button>
        ))}
      </div>
    </section>
  );
}

const COMMITTEE_QUICK_ITEMS = [
  { icon: '🏛️', name: '의회운영위' },
  { icon: '🚆', name: '건설교통위' },
  { icon: '💼', name: '기획재정위' },
  { icon: '🏥', name: '보건복지위' },
];

export default function DashboardLeftFilters() {
  return (
    <aside className="bg-white rounded-lg border border-gray-200 p-4" aria-label="좌측 칼럼 필터">
      <h3 className="text-base font-semibold text-gray-900">필터 탐색</h3>
      <p className="mt-1 text-xs text-gray-500">실데이터 연동 전 UI 스켈레톤입니다.</p>

      <section className="mt-4" aria-label="위원회 탐색">
        <h4 className="text-sm font-semibold text-gray-900">위원회 탐색</h4>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
          {COMMITTEE_QUICK_ITEMS.map((committee) => (
            <button
              key={committee.name}
              type="button"
              className="rounded-md border border-gray-200 bg-white px-2 py-2 text-left hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <span className="block text-base" aria-hidden="true">{committee.icon}</span>
              <span className="mt-1 block text-xs font-medium text-gray-700">{committee.name}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="mt-4 space-y-3">
        <FilterSection title="가나다" items={['ㄱ~ㄷ', 'ㄹ~ㅂ', 'ㅅ~ㅇ', 'ㅈ~ㅎ']} />
        <FilterSection title="정당" items={['더불어민주당', '국민의힘', '정의당', '무소속']} />
        <FilterSection title="지역" items={['수원', '고양', '성남', '용인']} />
      </div>
    </aside>
  );
}
