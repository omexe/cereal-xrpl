import { useEffect, useState } from 'react';
import { Agentation } from 'agentation';

/** Agentation is desktop-only; keep the mobile composer unobstructed. */
export function DevelopmentFeedback() {
  const [desktop, setDesktop] = useState(() => window.matchMedia('(min-width: 761px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(min-width: 761px)');
    const update = () => setDesktop(query.matches);
    query.addEventListener('change', update);
    update();
    return () => query.removeEventListener('change', update);
  }, []);
  return desktop ? <Agentation endpoint="http://localhost:4747" appName="Cereal" /> : null;
}
