import { MagnifyingGlassIcon } from '@radix-ui/react-icons';
import { Badge, Box, Button, Callout, Flex, Text, TextField } from '@radix-ui/themes';

import type { Agent } from '../types';
import { statusColor } from '../utils';

type Props = {
  agents: Agent[];
  agentFilter: string;
  query: string;
  onToggleAgent: (id: string) => void;
  onQueryChange: (value: string) => void;
};

export function AgentBar({ agents, agentFilter, query, onToggleAgent, onQueryChange }: Props) {
  const offline = agents.filter((agent) => agent.error);
  return (
    <Box px="4" className="agentbar">
      <Flex direction="column" gap="2" py="2" className="page-inner">
        <Flex align="center" justify="between" gap="3" wrap="wrap">
        <Flex align="center" gap="2" wrap="wrap">
          {agents.length ? (
            agents.map((agent) => (
              <Button
                key={agent.id}
                size="1"
                variant={agentFilter === agent.id ? 'solid' : 'soft'}
                color={statusColor(agent.status)}
                onClick={() => onToggleAgent(agent.id)}
              >
                <Badge
                  variant="solid"
                  color={statusColor(agent.status)}
                  radius="full"
                  className="status-dot"
                />
                {agent.id}
                {agent.ssh_proxy ? ' · proxy' : ''}
              </Button>
            ))
          ) : (
            <Text size="1" color="gray">
              暂无 agent 信息
            </Text>
          )}
        </Flex>
        <TextField.Root
          size="1"
          placeholder="搜索 repo / instance / alias"
          value={query}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          style={{ minWidth: 220 }}
        >
          <TextField.Slot>
            <MagnifyingGlassIcon height="14" width="14" />
          </TextField.Slot>
        </TextField.Root>
      </Flex>
        {offline.map((agent) => (
          <Callout.Root key={agent.id} color="red" size="1">
            <Callout.Text>
              {agent.id}: {agent.error}
            </Callout.Text>
          </Callout.Root>
        ))}
      </Flex>
    </Box>
  );
}
