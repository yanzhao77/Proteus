import type { FactoryAdapters } from '../models';
import { authorityPendingAdapters } from './adapters';
import { developmentFixtureAdapters } from './fixtureAdapters';
import { productApiAdapters } from './productApiAdapters';

/** Development fixture is intentionally impossible to select from a production build. */
export const createAdapters = (): FactoryAdapters => {
  if (import.meta.env.DEV && import.meta.env.VITE_PROTEUS_DEMO === 'true') return developmentFixtureAdapters();
  if (import.meta.env.VITE_PRODUCT_API_READS === 'false') return authorityPendingAdapters();
  return productApiAdapters();
};
