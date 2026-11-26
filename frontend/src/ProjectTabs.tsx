import {useEffect, useRef, type KeyboardEvent} from 'react';
import {Archive} from 'lucide-react';
import type {Row} from './api';

export default function ProjectTabs({projects, selectedId, onSelect}: {
  projects: Row[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  const tabs = projects;
  const selectedExists = tabs.some(project => project.id === selectedId);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }, [selectedId, selectedExists]);

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    onSelect(tabs[next].id);
    list.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }

  if (!tabs.length) return null;
  return <div className="project-switcher">
    <div ref={list} className="project-tabs" role="tablist" aria-label="项目切换">
      {tabs.map((project, index) => <button
        key={project.id}
        id={'project-tab-' + project.id}
        role="tab"
        aria-selected={project.id === selectedId}
        aria-controls="project-workspace"
        tabIndex={project.id === selectedId ? 0 : -1}
        className="project-tab"
        title={project.name + (project.archived ? '（已归档）' : '')}
        onClick={() => onSelect(project.id)}
        onKeyDown={event => navigate(event, index)}
      ><span>{project.name}</span>{project.archived && <Archive size={14} aria-label="已归档"/>}</button>)}
    </div>
  </div>;
}
