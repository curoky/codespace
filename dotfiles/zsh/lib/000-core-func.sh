function source_if_exists() {
  local target=${1}
  [[ -s ${target} ]] && source ${target}
}

function mkdir_if_not_exists() {
  if [[ ! -d $1 ]]; then
    mkdir -p $1
  fi
}

function PATH_REMOVE() {
  local DIR=$1
  export PATH=$(echo -n $PATH | awk -v RS=: -v ORS=: '$0 != "'$DIR'"' | sed 's/:$//')
}

function PATH_REMOVE_CONTAIN() {
  local DIR=$1
  export PATH=$(echo ${PATH} | awk -v RS=: -v ORS=: '/'$DIR'/ {next} {print}' | sed 's/:*$//')
}

function PATH_PUSH_FRONT() {
  local DIR=$1
  [ -d "${DIR}" ] && export PATH=${DIR}:$PATH #|| echo "${DIR} does not exist"
}

function PATH_PUSH_BACK() {
  local DIR=$1
  [ -d "${DIR}" ] && export PATH=$PATH:${DIR} #|| echo "${DIR} does not exist"
}

function FPATH_PUSH_FRONT() {
  local DIR=$1
  [ -d "${DIR}" ] && fpath=(${DIR} $fpath) #|| echo "${DIR} does not exist"
}
