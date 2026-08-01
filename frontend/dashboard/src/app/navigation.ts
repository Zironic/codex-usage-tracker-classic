import { ChartNoAxesCombined, type LucideIcon } from 'lucide-react';
import { isDashboardViewId, type DashboardViewId } from '../routes/dashboardSearch';
import {
  evidenceConsolePrimaryRoutes,
  evidenceConsoleSettingsRoute,
} from './evidenceConsoleRoutes';

export type ViewId = DashboardViewId;

export type NavItem = {
  id: ViewId;
  label: string;
  description: string;
  icon: LucideIcon;
};

const primary = evidenceConsolePrimaryRoutes.map(({ id, label, description, icon }) => ({
  id, label, description, icon,
}));

export const navItems: NavItem[] = [
  primary[0],
  {
    id: 'reports',
    label: 'Statistics',
    description: 'Usage distributions and trends',
    icon: ChartNoAxesCombined,
  },
  ...primary.slice(1),
];

export const settingsNavItem: NavItem = evidenceConsoleSettingsRoute;

export function isViewId(value: string | null): value is ViewId {
  return isDashboardViewId(value);
}
