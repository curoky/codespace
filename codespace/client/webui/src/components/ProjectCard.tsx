import { PlusIcon } from '@radix-ui/react-icons';
import { Badge, Button, Card, Flex, Separator, Text } from '@radix-ui/themes';

import type { InstanceCard, Project } from '../types';
import { providerColor } from '../utils';
import { InstanceRow } from './InstanceRow';

type Props = {
  project: Project;
  onCreateDefault: (project: Project) => void;
  onNewInstance: (project: Project) => void;
  onConnectCopied: (message: string, ok: boolean) => void;
  onDelete: (card: InstanceCard, purge: boolean) => void;
  onDismissOperation: (card: InstanceCard) => void;
};

/** A project card: header + either an empty-state CTA or its instance rows. */
export function ProjectCard({
  project,
  onCreateDefault,
  onNewInstance,
  onConnectCopied,
  onDelete,
  onDismissOperation,
}: Props) {
  const { instances } = project;

  return (
    <Card size="2" className="project-card">
      <Flex direction="column" gap="3">
        <Flex align="center" justify="between" gap="3" wrap="wrap">
          <Flex align="center" gap="2" minWidth="0" style={{ flex: '1 1 320px' }}>
            <Text weight="bold" truncate>
              {project.id}
            </Text>
            <Badge color={providerColor(project.provider)} variant="soft">
              {project.provider}
            </Badge>
            <Badge variant="surface" color="gray">
              {project.agent}
            </Badge>
            <Text size="2" color="gray" truncate>
              {project.description || project.repo}
            </Text>
          </Flex>
          <Flex align="center" gap="2" flexShrink="0">
            <Badge variant="surface" color="gray">
              {instances.length} 个环境
            </Badge>
            {project.known && (
              <Button size="2" variant="soft" onClick={() => onNewInstance(project)}>
                <PlusIcon />
                New instance
              </Button>
            )}
          </Flex>
        </Flex>

        {instances.length === 0 ? (
          <Flex align="center" justify="between" gap="3" wrap="wrap" className="project-empty">
            <Text size="2" color="gray">
              还没有环境。
            </Text>
            <Button size="2" onClick={() => onCreateDefault(project)}>
              <PlusIcon />
              Create
            </Button>
          </Flex>
        ) : (
          <Flex direction="column">
            {instances.map((card, index) => (
              <div key={card.key}>
                {index > 0 && <Separator size="4" my="1" />}
                <InstanceRow
                  card={card}
                  onConnectCopied={onConnectCopied}
                  onDelete={onDelete}
                  onDismissOperation={onDismissOperation}
                />
              </div>
            ))}
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
