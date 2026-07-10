import { UpdateIcon } from '@radix-ui/react-icons';
import { Button, Flex, Heading } from '@radix-ui/themes';

import type { GitProvider, TokenStatusResponse } from '../types';
import { TokenPopover } from './TokenPopover';

type Props = {
  refreshing: boolean;
  tokenStatus: TokenStatusResponse;
  onRefresh: () => void;
  onSaveToken: (provider: GitProvider, token: string) => Promise<boolean>;
};

export function TopBar({ refreshing, tokenStatus, onRefresh, onSaveToken }: Props) {
  return (
    <Flex asChild align="center" justify="between" gap="3" px="4" py="3" className="topbar">
      <header>
        <Heading size="5">Codespace</Heading>
        <Flex align="center" gap="2">
          <TokenPopover status={tokenStatus} onSave={onSaveToken} />
          <Button variant="soft" color="gray" onClick={onRefresh} loading={refreshing}>
            <UpdateIcon />
            Refresh
          </Button>
        </Flex>
      </header>
    </Flex>
  );
}
