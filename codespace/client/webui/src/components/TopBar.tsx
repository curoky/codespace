import { UpdateIcon } from '@radix-ui/react-icons';
import { Box, Button, Flex, Heading, Text } from '@radix-ui/themes';

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
    <Box asChild px="4" className="topbar">
      <header>
        <Flex align="center" justify="between" gap="3" py="3" className="page-inner">
          <Flex align="center" gap="2">
            <Heading size="5">Codespace</Heading>
            <Text size="1" color="gray">
              项目开发环境
            </Text>
          </Flex>
          <Flex align="center" gap="2">
            <TokenPopover status={tokenStatus} onSave={onSaveToken} />
            <Button variant="soft" color="gray" onClick={onRefresh} loading={refreshing}>
              <UpdateIcon />
              Refresh
            </Button>
          </Flex>
        </Flex>
      </header>
    </Box>
  );
}
