import { MagnifyingGlassIcon } from '@radix-ui/react-icons';
import {
  Badge,
  Box,
  Button,
  Callout,
  Code,
  Dialog,
  Flex,
  ScrollArea,
  Text,
  TextField,
} from '@radix-ui/themes';
import { useMemo, useState } from 'react';

import type { ConfigSummary, CreateForm } from '../types';
import { instanceAlias, providerColor } from '../utils';

type TemplateOption = ConfigSummary['templates'][number] & { resolvedAgent: string };

type Props = {
  open: boolean;
  config: ConfigSummary | null;
  form: CreateForm;
  error: string | null;
  submitting: boolean;
  providerHasToken: boolean;
  onOpenChange: (open: boolean) => void;
  onSelectTemplate: (templateId: string) => void;
  onInstanceChange: (value: string) => void;
  onSubmit: () => void;
};

export function CreateDialog({
  open,
  config,
  form,
  error,
  submitting,
  providerHasToken,
  onOpenChange,
  onSelectTemplate,
  onInstanceChange,
  onSubmit,
}: Props) {
  const [query, setQuery] = useState('');

  const options = useMemo<TemplateOption[]>(() => {
    if (!config) return [];
    return config.templates
      .map((template) => ({ ...template, resolvedAgent: template.agent || config.default_agent }))
      .filter((template) => {
        if (!query) return true;
        return `${template.id} ${template.repo}`.toLowerCase().includes(query.toLowerCase());
      });
  }, [config, query]);

  const selected = config?.templates.find((template) => template.id === form.template) ?? null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="480px">
        <Dialog.Title>New codespace</Dialog.Title>
        <Dialog.Description size="2" color="gray" mb="3">
          选择 template 并填写 instance 名，其余字段由 template 与 defaults 填充。
        </Dialog.Description>

        <Flex direction="column" gap="3">
          {error && (
            <Callout.Root color="red" size="1">
              <Callout.Text>{error}</Callout.Text>
            </Callout.Root>
          )}

          <Box>
            <Text size="2" weight="bold" as="div" mb="1">
              Template
            </Text>
            <TextField.Root
              size="2"
              placeholder="过滤 template"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              mb="2"
            >
              <TextField.Slot>
                <MagnifyingGlassIcon height="14" width="14" />
              </TextField.Slot>
            </TextField.Root>
            <ScrollArea type="auto" style={{ maxHeight: 180 }}>
              <Flex direction="column" gap="1">
                {options.length === 0 && (
                  <Box p="2">
                    <Text size="2" color="gray">
                      没有匹配的 template。
                    </Text>
                  </Box>
                )}
                {options.map((template) => (
                  <Button
                    key={template.id}
                    variant={form.template === template.id ? 'solid' : 'soft'}
                    color={form.template === template.id ? undefined : 'gray'}
                    onClick={() => onSelectTemplate(template.id)}
                    style={{ justifyContent: 'flex-start', height: 'auto', padding: 8 }}
                  >
                    <Flex direction="column" align="start" gap="1" width="100%">
                      <Flex align="center" gap="2">
                        <Text weight="bold">{template.id}</Text>
                        <Badge color={providerColor(template.provider)} variant="soft">
                          {template.provider}
                        </Badge>
                        <Badge variant="surface" color="gray">
                          {template.resolvedAgent}
                        </Badge>
                      </Flex>
                      <Text size="1" color="gray">
                        {template.description || template.repo}
                      </Text>
                    </Flex>
                  </Button>
                ))}
              </Flex>
            </ScrollArea>
          </Box>

          {selected && (
            <>
              {!providerHasToken && (
                <Callout.Root color="amber" size="1">
                  <Callout.Text>
                    请先在右上角 Tokens 中保存 {form.provider === 'gitlab' ? 'GitLab' : 'GitHub'} token。
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
                  value={form.instance}
                  onChange={(event) => onInstanceChange(event.currentTarget.value)}
                />
              </Box>
              <Callout.Root color="gray" size="1">
                <Callout.Text>
                  Local SSH alias:{' '}
                  <Code>{instanceAlias(form.agent, form.template, form.instance) || '-'}</Code>
                </Callout.Text>
              </Callout.Root>
            </>
          )}

          <Flex gap="3" mt="1" justify="end">
            <Dialog.Close>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </Dialog.Close>
            <Button onClick={onSubmit} loading={submitting} disabled={!selected}>
              Create
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
