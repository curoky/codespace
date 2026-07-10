import { CheckCircledIcon, KeyboardIcon } from '@radix-ui/react-icons';
import { Badge, Button, Flex, IconButton, Popover, Text, TextField } from '@radix-ui/themes';
import { useState } from 'react';

import type { GitProvider, TokenStatusResponse } from '../types';

type Props = {
  status: TokenStatusResponse;
  onSave: (provider: GitProvider, token: string) => Promise<boolean>;
};

const PROVIDERS: Array<{ id: GitProvider; label: string }> = [
  { id: 'github', label: 'GitHub' },
  { id: 'gitlab', label: 'GitLab' },
];

/** Provider tokens live behind a popover instead of occupying the top bar. */
export function TokenPopover({ status, onSave }: Props) {
  const [values, setValues] = useState<Record<GitProvider, string>>({ github: '', gitlab: '' });
  const savedCount = PROVIDERS.filter((p) => status[p.id].has_token).length;

  async function save(provider: GitProvider) {
    const ok = await onSave(provider, values[provider]);
    if (ok) setValues((current) => ({ ...current, [provider]: '' }));
  }

  return (
    <Popover.Root>
      <Popover.Trigger>
        <Button variant="soft" color={savedCount === PROVIDERS.length ? 'green' : 'gray'}>
          <KeyboardIcon />
          Tokens
          <Badge variant="solid" color={savedCount ? 'green' : 'gray'} radius="full">
            {savedCount}/{PROVIDERS.length}
          </Badge>
        </Button>
      </Popover.Trigger>
      <Popover.Content width="320px">
        <Flex direction="column" gap="3">
          <Text size="2" color="gray">
            Token 只保存在本地 Python service 进程内存中。
          </Text>
          {PROVIDERS.map((provider) => (
            <Flex key={provider.id} direction="column" gap="1">
              <Flex align="center" gap="2">
                <Text size="2" weight="bold">
                  {provider.label}
                </Text>
                {status[provider.id].has_token && (
                  <Badge color="green" variant="soft">
                    <CheckCircledIcon /> saved
                  </Badge>
                )}
              </Flex>
              <Flex gap="2">
                <TextField.Root
                  style={{ flex: 1 }}
                  type="password"
                  size="2"
                  placeholder={status[provider.id].has_token ? '已保存，可覆盖' : `${provider.label} token`}
                  value={values[provider.id]}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [provider.id]: event.currentTarget.value }))
                  }
                />
                <Button size="2" onClick={() => void save(provider.id)}>
                  Save
                </Button>
              </Flex>
            </Flex>
          ))}
        </Flex>
      </Popover.Content>
    </Popover.Root>
  );
}
