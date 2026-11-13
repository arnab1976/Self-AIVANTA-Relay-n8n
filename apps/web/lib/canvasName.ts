export const NAME_SEP = ' · ';

export interface ProjectInfo {
  id: string;
  code: string;
  name: string;
  client?: string;
}

/** Prefix canvases as `{project code} · {RFP intake name}` so versions of the same intake are identifiable. */
export function intakePrefix(project?: ProjectInfo | null): string {
  if (!project) return '';
  return `${project.code}${NAME_SEP}${project.name}`;
}

export function composeCanvasName(project: ProjectInfo | null | undefined, label: string): string {
  const clean = label.trim() || 'Canvas';
  const prefix = intakePrefix(project);
  return prefix ? `${prefix}${NAME_SEP}${clean}` : clean;
}

export function stripIntakePrefix(fullName: string, project?: ProjectInfo | null): string {
  const prefix = intakePrefix(project);
  if (prefix && fullName.startsWith(`${prefix}${NAME_SEP}`)) return fullName.slice(prefix.length + NAME_SEP.length);
  const parts = fullName.split(NAME_SEP);
  if (parts.length >= 3 && /^[A-Z]{2,}-\d+/.test(parts[0])) return parts.slice(2).join(NAME_SEP);
  return fullName;
}
