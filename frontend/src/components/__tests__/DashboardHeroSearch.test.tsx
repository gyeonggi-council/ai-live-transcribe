import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import DashboardHeroSearch from '../DashboardHeroSearch';

describe('DashboardHeroSearch', () => {
  it('renders all scope tabs with tab semantics', () => {
    render(
      <DashboardHeroSearch
        selectedScope="all"
        onScopeChange={jest.fn()}
        query=""
        onQueryChange={jest.fn()}
      />,
    );

    expect(screen.getByRole('tablist', { name: '검색 범위' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '전체' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '본회의' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByPlaceholderText('예: GTX 착공')).toBeInTheDocument();
  });

  it('changes scope when tab is clicked', async () => {
    const user = userEvent.setup();
    const handleScopeChange = jest.fn();

    render(
      <DashboardHeroSearch
        selectedScope="all"
        onScopeChange={handleScopeChange}
        query=""
        onQueryChange={jest.fn()}
      />,
    );

    await user.click(screen.getByRole('tab', { name: '의원 발언' }));

    expect(handleScopeChange).toHaveBeenCalledWith('speech');
  });
});
