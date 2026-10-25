import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { isLive } from './mode';
import ResearchChat from './ResearchChat';
import { useResearchRunner } from './workspaceStore';
import { DevelopmentFeedback } from './components/DevelopmentFeedback';
import './tokens.css';
import './styles.css';
import './research.css';

function DemoApp() {
  useResearchRunner(!isLive);
  if (window.location.pathname === '/demo-chat') return isLive
    ? <main><h1>Research chat requires mock mode</h1><p>Start the frontend with <code>npm run dev:mock</code>, then open Developer tools in Settings.</p><a href="/">Back to Cereal</a></main>
    : <ResearchChat />;
  return <App />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <>
    <React.StrictMode><DemoApp /></React.StrictMode>
    {import.meta.env.DEV && <DevelopmentFeedback />}
  </>,
);
