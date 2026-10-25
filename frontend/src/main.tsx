import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { isLive, isTestEnvironment } from './mode';
import ResearchChat from './ResearchChat';
import LiveResearchChat from './LiveResearchChat';
import { useResearchRunner } from './workspaceStore';
import { DevelopmentFeedback } from './components/DevelopmentFeedback';
import './tokens.css';
import './styles.css';
import './research.css';

function DemoApp() {
  useResearchRunner(!isLive);
  const path = window.location.pathname.replace(/\/$/, '');
  if (path === '/test-chat' || (path === '/demo-chat' && isLive)) return <LiveResearchChat />;
  if ((isTestEnvironment && path === '/fixture-chat') || path === '/demo-chat') return <ResearchChat />;
  return <App />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <>
    <React.StrictMode><DemoApp /></React.StrictMode>
    {import.meta.env.DEV && <DevelopmentFeedback />}
  </>,
);
