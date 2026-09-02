set number
set cursorline
set autoread
set confirm
set hlsearch
set mouse=a
set tabstop=2
set shiftwidth=2
set expandtab
set backspace=2

let s:plugin_path = '/opt/bm/store/vim-plugins/share/vim-plugin'
if exists('$VIM_PLUGIN_PATH') && !empty($VIM_PLUGIN_PATH)
  let s:plugin_path = $VIM_PLUGIN_PATH
endif

if isdirectory(s:plugin_path)
  execute 'set runtimepath+=' . fnameescape(s:plugin_path)
  call plug#begin(s:plugin_path . '/plugged')
  Plug 'Raimondi/delimitMate'
  Plug 'vim-airline/vim-airline'
  Plug 'vim-airline/vim-airline-themes'
  Plug 'altercation/vim-colors-solarized'
  Plug 'Yggdroot/indentLine'
  Plug 'tpope/vim-sleuth'
  Plug 'tpope/vim-commentary'
  Plug 'tpope/vim-fugitive'
  Plug 'airblade/vim-gitgutter'
  Plug 'preservim/nerdtree'
  Plug 'Xuyuanp/nerdtree-git-plugin'
  call plug#end()

  let g:airline_theme = 'solarized'
  let g:airline#extensions#tabline#enabled = 1
  let g:airline#extensions#tabline#formatter = 'unique_tail_improved'
  set updatetime=500
  syntax enable
  set background=light
  colorscheme solarized
  map <C-n> :NERDTreeToggle<CR>
endif
