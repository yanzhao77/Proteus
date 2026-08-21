import type { FactoryAdapters } from '../models';
import { developmentFixtureAdapters } from './fixtureAdapters';
import { productApiAdapters } from './productApiAdapters';

/** Development fixture is intentionally impossible to select from a production build. */
export const createAdapters = (): FactoryAdapters => {
  if (import.meta.env.DEV && import.meta.env.VITE_PROTEUS_DEMO === 'true') return developmentFixtureAdapters();
  // Production has one supported read surface: the real Product API. A browser
  // flag must never silently replace it with a fixture or authority placeholder.
  return productApiAdapters();
};
