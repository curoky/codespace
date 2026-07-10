import { CopyIcon, DotsHorizontalIcon, ExternalLinkIcon } from '@radix-ui/react-icons';
import {
  Badge,
  Box,
  Button,
  Card,
  Code,
  DropdownMenu,
  Flex,
  IconButton,
  Progress,
  Spinner,
  Text,
} from '@radix-ui/themes';

import type { InstanceCard } from '../types';
import {
  connectCommand,
  copyToClipboard,
  isCodespaceCard,
  operationProgress,
  providerColor,
  statusColor,
} from '../utils';

type Props = {
  card: InstanceCard;
  onConnectCopied: (message: string, ok: boolean) => void;
  onDelete: (card: InstanceCard, purge: boolean) => void;
  onDismissOperation: (card: InstanceCard) => void;
};

export function CodespaceCard({ card, onConnectCopied, onDelete, onDismissOperation }: Props) {
  const codespace = isCodespaceCard(card);

  async function copyConnect() {
    const command = connectCommand(card);
    if (!command) return;
    const ok = await copyToClipboard(command);
    onConnectCopied(ok ? `已复制：${command}` : '复制失败', ok);
  }

  return (
    <Card size="2" className={`cs-card ${card.kind === 'operation' ? 'cs-card-op' : ''}`}>
      <Flex direction="column" gap="2" height="100%">
        <Flex align="center" justify="between" gap="2">
          <Flex align="center" gap="2" minWidth="0">
            <Text weight="bold" truncate>
              {card.instance}
            </Text>
            <Badge color={statusColor(card.status)} variant="soft">
              {card.kind === 'operation' ? (
                <>
                  <Spinner size="1" /> {card.status}
                </>
              ) : (
                card.status || 'unknown'
              )}
            </Badge>
          </Flex>
          <Badge variant="surface" color="gray">
            {card.template}
          </Badge>
        </Flex>

        <Flex align="center" gap="2" minWidth="0">
          <Badge color={providerColor(card.provider)} variant="soft">
            {card.provider}
          </Badge>
          <Text size="2" color="gray" truncate>
            {card.repo}
          </Text>
        </Flex>

        <Flex align="center" gap="2">
          <Badge variant="surface" color="gray">
            {card.agent_id}
          </Badge>
          {card.alias && (
            <Code size="1" truncate>
              {card.alias}
            </Code>
          )}
        </Flex>

        {card.kind === 'operation' && (
          <Box>
            <Progress
              size="1"
              value={operationProgress(card.status)}
              color={statusColor(card.status)}
            />
            {card.stage && (
              <Text size="1" color="gray" mt="1" as="div">
                {card.stage}
              </Text>
            )}
            {card.error && (
              <Text size="1" color="red" mt="1" as="div">
                {card.error}
              </Text>
            )}
          </Box>
        )}

        <Box flexGrow="1" />

        {codespace ? (
          <Flex align="center" gap="2">
            <Button asChild size="2" style={{ flex: 1 }}>
              <a href={card.trae_url}>
                <ExternalLinkIcon />
                Open in Trae
              </a>
            </Button>
            <Button size="2" variant="soft" color="gray" onClick={() => void copyConnect()}>
              <CopyIcon />
              SSH
            </Button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <IconButton size="2" variant="soft" color="gray">
                  <DotsHorizontalIcon />
                </IconButton>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content>
                <DropdownMenu.Item color="red" onClick={() => onDelete(card, false)}>
                  Delete container
                </DropdownMenu.Item>
                <DropdownMenu.Item color="red" onClick={() => onDelete(card, true)}>
                  Delete workspace
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </Flex>
        ) : (
          card.status === 'failed' && (
            <Button size="2" variant="soft" color="gray" onClick={() => onDismissOperation(card)}>
              Dismiss
            </Button>
          )
        )}
      </Flex>
    </Card>
  );
}
