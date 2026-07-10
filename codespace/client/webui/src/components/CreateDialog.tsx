import {
  Badge,
  Box,
  Button,
  Callout,
  Code,
  Dialog,
  Flex,
  Text,
  TextField,
} from '@radix-ui/themes';

import type { Project } from '../types';
import { instanceAlias, providerColor } from '../utils';

type Props = {
  project: Project | null;
  instance: string;
  submitting: boolean;
  providerHasToken: boolean;
  onOpenChange: (open: boolean) => void;
  onInstanceChange: (value: string) => void;
  onSubmit: () => void;
};

/** Create another instance for a fixed project (template). Only the name is editable. */
export function CreateDialog({
  project,
  instance,
  submitting,
  providerHasToken,
  onOpenChange,
  onInstanceChange,
  onSubmit,
}: Props) {
  return (
    <Dialog.Root open={project !== null} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="440px">
        <Dialog.Title>New instance</Dialog.Title>
        <Dialog.Description size="2" color="gray" mb="3">
          为项目创建一个新的运行环境。repo、provider、agent、镜像由项目配置填充。
        </Dialog.Description>

        {project && (
          <Flex direction="column" gap="3">
            <Flex align="center" gap="2" wrap="wrap">
              <Text weight="bold">{project.id}</Text>
              <Badge color={providerColor(project.provider)} variant="soft">
                {project.provider}
              </Badge>
              <Badge variant="surface" color="gray">
                {project.agent}
              </Badge>
              <Text size="2" color="gray" truncate>
                {project.repo}
              </Text>
            </Flex>

            {!providerHasToken && (
              <Callout.Root color="amber" size="1">
                <Callout.Text>
                  请先在右上角 Tokens 中保存 {project.provider === 'gitlab' ? 'GitLab' : 'GitHub'} token。
                </Callout.Text>
              </Callout.Root>
            )}

            <Box>
              <Text size="2" weight="bold" as="div" mb="1">
                Instance name
              </Text>
              <TextField.Root
                size="2"
                autoFocus
                value={instance}
                onChange={(event) => onInstanceChange(event.currentTarget.value)}
              />
            </Box>

            <Callout.Root color="gray" size="1">
              <Callout.Text>
                Local SSH alias:{' '}
                <Code>{instanceAlias(project.agent, project.id, instance) || '-'}</Code>
              </Callout.Text>
            </Callout.Root>

            <Flex gap="3" mt="1" justify="end">
              <Dialog.Close>
                <Button variant="soft" color="gray">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button onClick={onSubmit} loading={submitting} disabled={!instance.trim()}>
                Create
              </Button>
            </Flex>
          </Flex>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
