if [ -d "friendly-telegram" ]; then
  PYVER=""
  if echo "$OSTYPE" | grep -qE '^linux-gnu.*'; then
    PYVER="3"
  fi
  if [ -d "friendly-telegram/friendly-telegram" ]; then
    cd friendly-telegram
  fi
  "python$PYVER" -m friendly-telegram $@
  exit $?
fi


if echo "$OSTYPE" | grep -qE '^linux-gnu.*'; then
  if [ ! "$(whoami)" = "root" ]; then
    # Relaunch as root, preserving arguments
    sudo "$SHELL" -c '$SHELL <('"$(which curl >/dev/null && echo 'curl -Ls' || echo 'wget -qO-')"' https://git.io/JeOXn) '"$@"
    exit $?
  fi
  PKGMGR="apt install -y"
  apt update
  PYVER="3"
elif [ "$OSTYPE" = "linux-android" ]; then
  PKGMGR="pkg install -y"
  PYVER=""
elif echo "$OSTYPE" | grep -qE '^darwin.*'; then
  if which brew; then
    echo "brew detected"
  else
    ruby <(curl -fsSk https://raw.github.com/mxcl/homebrew/go)
  fi
  PKGMGR="brew install"
  PYVER="3"
  SKIP_OPTIONAL="1"
  echo "macOS not yet supported by automated install script. Please go to https://github.com/friendly-telegram/friendly-telegram/#mac-os-x"
else
  echo "Unrecognised OS. Please follow https://github.com/friendly-telegram/friendly-telegram/blob/master/README.md"
  exit 1
fi

$PKGMGR "python$PYVER" git || { echo "Core install failed."; exit 2; }

if [ ! "$SKIP_OPTIONAL" = "1" ]; then
  if [ ! "$OSTYPE" = "linux-android" ]; then
    $PKGMGR "python$PYVER-dev" || echo "Python-dev install failed."
    $PKGMGR "python$PYVER-pip" || echo "Python-pip install failed."
    $PKGMGR build-essential libwebp-dev libz-dev libjpeg-dev libffi-dev libcairo2 libopenjp2-7 libtiff5 libcairo2-dev || echo "Stickers install failed."
    $PKGMGR neofetch || echo "Utilities install failed."
    $PKGMGR dialog || echo "UI install failed."
  else
    $PKGMGR libjpeg-turbo libwebp libffi libcairo build-essential dialog neofetch || echo "Optional installation failed."
  fi
else
  $PKGMGR neofetch dialog || echo "GUI installation failed"
fi  # FI @dil3mm4

if [ ! x"$SUDO_USER" = x"" ]; then
  SUDO_CMD="sudo -u $SUDO_USER "
else
  SUDO_CMD=""
fi

[ -d friendly-telegram ] || ${SUDO_CMD}rm -rf friendly-telegram
${SUDO_CMD}git clone https://github.com/friendly-telegram/friendly-telegram || { echo "Clone failed."; exit 3; }
cd friendly-telegram
${SUDO_CMD}"python$PYVER" -m pip install cryptg || echo "Cryptg failed"
${SUDO_CMD}"python$PYVER" -m pip install -r requirements.txt || { echo "Requirements failed!"; exit 4; }
${SUDO_CMD}"python$PYVER" -m friendly-telegram && python$PYVER -m friendly-telegram $@ || { echo "Python scripts failed"; exit 5; }
