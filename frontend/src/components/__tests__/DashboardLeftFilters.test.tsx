import { render, screen } from '@testing-library/react';

import DashboardLeftFilters from '../DashboardLeftFilters';

describe('DashboardLeftFilters', () => {
  it('renders committee navigation and speaker filter skeleton sections', () => {
    render(<DashboardLeftFilters />);

    expect(screen.getByRole('heading', { name: '위원회 탐색' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /건설교통위/i })).toBeInTheDocument();

    expect(screen.getByRole('heading', { name: '가나다' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '정당' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '지역' })).toBeInTheDocument();
  });
});
