import { CopyIcon, DotsHorizontalIcon, ExternalLinkIcon } from '@radix-ui/react-icons';
import { Badge, Box, Button, Code, DropdownMenu, Flex, IconButton, Progress, Spinner, Text } from '@radix-ui/themes';

import type { InstanceCard } from '../types';
import { connectCommand, copyToClipboard, isCodespaceCard, operationProgress, statusColor } from '../utils';

type Props = {
  card: InstanceCard;
  onConnectCopied: (message: string, ok: boolean) => void;
  onDelete: (card: InstanceCard, purge: boolean) => void;
  onDismissOperation: (card: InstanceCard) => void;
};

/** One environment row inside a project card: a ready codespace or an in-flight create. */
export function InstanceRow({ card, onConnectCopied, onDelete, onDismissOperation }: Props) {
  const codespace = isCodespaceCard(card);

  async function copyConnect() {
    const command = connectCommand(card);
    if (!command) return;
    const ok = await copyToClipboard(command);
    onConnectCopied(ok ? `已复制：${command}` : '复制失败', ok);
  }

  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      wrap="wrap"
      className={`instance-row ${card.kind === 'operation' ? 'instance-row-op' : ''}`}
    >
      <Flex align="center" gap="2" minWidth="0" style={{ flex: '1 1 240px' }}>
        <Text weight="medium" truncate>
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
        {card.alias && (
          <Code size="1" truncate>
            {card.alias}
          </Code>
        )}
      </Flex>

      {codespace ? (
        <Flex align="center" gap="2" flexShrink="0">
          <Button asChild size="2">
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
        <Flex align="center" gap="2" minWidth="0" style={{ flex: '1 1 220px' }}>
          <Box flexGrow="1" minWidth="0">
            <Progress size="1" value={operationProgress(card.status)} color={statusColor(card.status)} />
            {card.stage && (
              <Text size="1" color="gray" mt="1" as="div" truncate>
                {card.stage}
              </Text>
            )}
            {card.error && (
              <Text size="1" color="red" mt="1" as="div">
                {card.error}
              </Text>
            )}
          </Box>
          {card.status === 'failed' && (
            <Button size="2" variant="soft" color="gray" style={{ flexShrink: 0 }} onClick={() => onDismissOperation(card)}>
              Dismiss
            </Button>
          )}
        </Flex>
      )}
    </Flex>
  );
}
