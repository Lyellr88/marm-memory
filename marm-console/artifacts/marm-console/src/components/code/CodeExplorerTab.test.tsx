import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeExplorerTab } from './CodeExplorerTab';

let projects = [
  { name: 'alpha', path: 'C:/alpha', nodes: 4, edges: 3 },
];
let mountCount = 0;

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => ({ data: projects, isLoading: false }),
  useProjectGraph: () => ({ data: undefined, isLoading: false, isError: false }),
}));

vi.mock('./CodeGraphExplorer', async () => {
  const React = await import('react');
  return {
    CodeGraphExplorer: ({ project }: { project: { name: string } }) => {
      const [instance] = React.useState(() => ++mountCount);
      return <p data-testid="code-explorer">{`${project.name}:${instance}`}</p>;
    },
  };
});

afterEach(() => {
  cleanup();
  projects = [{ name: 'alpha', path: 'C:/alpha', nodes: 4, edges: 3 }];
  mountCount = 0;
});

describe('CodeExplorerTab', () => {
  it('remounts the graph explorer when the selected repository changes', async () => {
    const view = render(<CodeExplorerTab />);

    await screen.findByText('alpha:1');
    projects = [{ name: 'beta', path: 'C:/beta', nodes: 4, edges: 3 }];
    view.rerender(<CodeExplorerTab />);

    await waitFor(() => expect(screen.getByTestId('code-explorer').textContent).toBe('beta:2'));
  });
});
