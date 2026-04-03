import { motion, AnimatePresence } from 'framer-motion';
import {
  PanelRightClose,
  PanelRightOpen,
  ExternalLink,
  Database,
  FlaskConical,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useAppConfig } from '@/contexts/AppConfigContext';
import type {
  GenieSpaceResource,
  MlflowExperimentResource,
} from '@/contexts/AppConfigContext';

function ResourceLink({
  href,
  icon: Icon,
  label,
  sublabel,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  sublabel?: string;
}) {
  if (!href) return null;

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 transition-all hover:border-border hover:bg-accent"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-foreground">
          {label}
        </div>
        {sublabel && (
          <div className="truncate text-xs text-muted-foreground">
            {sublabel}
          </div>
        )}
      </div>
      <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
    </a>
  );
}

function ResourceSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function PanelContent({
  genieSpaces,
  mlflowExperiment,
}: {
  genieSpaces: GenieSpaceResource[];
  mlflowExperiment: MlflowExperimentResource | null;
}) {
  const hasGenieSpaces = genieSpaces.length > 0;
  const hasExperiment = !!mlflowExperiment;

  if (!hasGenieSpaces && !hasExperiment) {
    return (
      <div className="px-3 py-8 text-center text-sm text-muted-foreground">
        No connected resources
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {hasGenieSpaces && (
        <ResourceSection title="Genie Spaces">
          {genieSpaces.map((space) => (
            <ResourceLink
              key={space.id}
              href={space.url}
              icon={Database}
              label={space.name}
              sublabel={space.id.slice(0, 12) + '...'}
            />
          ))}
        </ResourceSection>
      )}

      {hasExperiment && (
        <ResourceSection title="MLflow">
          <ResourceLink
            href={mlflowExperiment.url}
            icon={FlaskConical}
            label="Experiment"
            sublabel={`ID: ${mlflowExperiment.id}`}
          />
        </ResourceSection>
      )}
    </div>
  );
}

export function ResourcePanelToggle({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  const { genieSpaces, mlflowExperiment } = useAppConfig();
  const totalResources =
    genieSpaces.length + (mlflowExperiment ? 1 : 0);

  if (totalResources === 0) return null;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            className="relative h-8 w-8"
            onClick={onToggle}
          >
            {open ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-medium text-primary-foreground">
              {totalResources}
            </span>
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <p>{open ? 'Hide' : 'Show'} connected resources</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function ResourcePanel({ open }: { open: boolean }) {
  const { genieSpaces, mlflowExperiment } = useAppConfig();

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="h-dvh shrink-0 overflow-hidden border-l bg-background"
        >
          <div className="flex h-full w-[280px] flex-col">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold">Resources</h2>
            </div>

            <div className="flex-1 overflow-y-auto px-1 py-3">
              <PanelContent
                genieSpaces={genieSpaces}
                mlflowExperiment={mlflowExperiment}
              />
            </div>

            <div className="border-t px-4 py-2">
              <p className="text-[11px] text-muted-foreground">
                Links open in the Databricks workspace
              </p>
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
