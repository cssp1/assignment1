# Dan Maas .bashrc
# executed by EVERY interactive bash
# mainly used for aliases
# environment variables belong in .bash_profile, NOT HERE!
# (except for $PS1)

# disable Ctrl-S "terminal stop" command which I keep hitting
# by accident
if [ "$PS1" ]; then # interactive shells only
	stty stop undef > /dev/null 2>&1
fi

# load completions
if [ "$PS1" ] && echo $BASH_VERSION | grep -q '^2' \
   && [ -f ~/.bash_completion ]; then # interactive shell
        # Source completion code
        . ~/.bash_completion
fi

RED="\[\033[0;31m\]"
YELLOW="\[\033[0;33m\]"
GREEN="\[\033[0;32m\]"
GRAY="\[\033[1;30m\]"
PINK="\[\033[0;35m\]"
LIGHT_GRAY="\[\033[0;37m\]"
CYAN="\[\033[0;36m\]"
LIGHT_CYAN="\[\033[1;36m\]"
NO_COLOR="\[\033[0m\]"

# my prompt
if [ "$UID" -eq 0 ]; then
    export PS1="$RED[\u@\h \w]$NO_COLOR "
else
	if [ "$DMAAS_OS" = macosx ]; then
		# Mac gets a happy color
		COLOR="$PINK"
	else
		COLOR="$YELLOW"
	fi
    # note: dmaas_parse_git_branch is from .bash_profile
    export PS1="$COLOR[\u@\h \w$GREEN\$(dmaas_parse_git_branch)$COLOR]$NO_COLOR "
    unset COLOR
fi


# default perms = rwx rwx r-x
umask 002

# make ls pretty
if [ "$DMAAS_OS" = "IRIX" ]; then
    alias ls='ls -lh'
elif [ "$DMAAS_OS" = cygwin ]; then
    alias ls='ls -l'
elif [ "$DMAAS_OS" = macosx ]; then
	alias ls='ls -lFh'
else
    alias ls='ls -lh --color=auto'
fi

# an ls variant that doesn't show intermediate files
alias dls='ls -I "*.pyc" -I "*.o"'
alias grep='grep --color=always --exclude-dir=\*.svn\*'
alias fh='find . -iname'
alias date='date -u' # always show date in UTC

# PS - show all procs, show wait info, show vm data
# VSZ = total VM size (KB), RSS = resident size (incl DLLs/shm)
if [ "$DMAAS_OS" = "IRIX" ]; then
    alias ps='ps -Af -o pid,user,vsz,rss,time,args'
elif [ "$DMAAS_OS" = macosx ]; then
    alias ps='ps ax -o pid,user,vsize,rss,time,stat,command'
else
    alias ps='ps afx -o pid,user,vsize,rss,time,stat,command'
fi

# I like these utils to read in KB, MB, etc
# instead of stupid UNIX "blocks"
alias df='df -h'
alias du='du -h'
alias free='free -m'

if [ ! "$UID" -eq 0 ]; then
	# do not tell SSH to forward X by default
	alias ssh='ssh -q'
else
	alias ssh='ssh -q'
fi

alias sd='ssh -q -X dcine2.dyndns.org'

# suppress GDB annoyance
alias gdb='gdb -quiet'

# tell wget to resume all downloads, and retry forever
alias wget='wget -t 0 -c'

alias lynx='lynx -force_secure -nopause -image_links'

# make BC into a useful calculator by loading the math library
alias bc='bc -l'

# sane options for a2ps
alias a2ps='a2ps -o - --portrait -1 --no-header --borders no'

# sane options for mkisofs (Joliet, Rock Ridge, long filenames...)
alias mkisofs='mkisofs -J -r -l'

alias rd='telnet render-server 9790'
alias ex='export DISPLAY=192.168.1.104:0; export GAMMA=2.0; export DMIN=260; export DWHITE=720;'
alias eh='export DISPLAY=homestar:0; export GAMMA=2.0; export DMIN=260; export DWHITE=720;'
alias em='export DISPLAY=marzipan:0; export GAMMA=2.0; export DMIN=260; export DWHITE=720;'

alias da='/shared/farm/do-on-all.sh'
alias dafast='HOSTS="render005 render006 render007 render008 render009 render010 render011 render012 render013 render015 render016 render017 render018" /shared/farm/do-on-all.sh'
alias daf="da 'free -m | grep buffers/cache'"
alias dap="da 'ps | grep interp'"
alias dak='/shared/farm/do-on-all.sh killall interp.bin interp.bin64 && /shared/farm/do-on-all.sh killall prman'
alias h='check-image -h -v'

alias gn='gnumeric /shared/proj/company/business-finances.gnumeric'
alias np='sudo netstat -np | grep EST'
alias v='viewer'
alias nt="nano $HOME/Dropbox/Personal/todo.txt"
alias svns='svn stat | grep -v \\?'

alias tiny='ssh -i $HOME/.ssh/id_rsa dmaas@awstiny.maasdigital.com -L8888:localhost:8888'
alias gm='ssh gamemaster.spinpunch.com'
alias mfprod='ssh mfprod-raw.spinpunch.com'
alias mf2prod='ssh mf2prod-raw.spinpunch.com'
alias bfmprod='ssh bfmprod-raw.spinpunch.com'
alias trprod='ssh trprod-raw.spinpunch.com'
alias sgprod='ssh sgprod-raw.spinpunch.com'
alias dvprod='ssh dvprod-raw.spinpunch.com'
alias forums='ssh forums-raw.spinpunch.com'
alias www='ssh www.spinpunch.com'
alias about='ssh about.spinpunch.com'
alias anal1='ssh analytics1.spinpunch.com'
alias mgd='./make-gamedata.sh -u && kill -HUP `cat server_*.pid` `cat proxyserver.pid`'

# update vpslink client website
alias outbox='/shared/proj/nasa/outbox/terra/mksite.sh && /shared/proj/nasa/outbox/terra/sync.sh'

# rename JPEG files according to date/time from EXIF header
alias jheadtime='jhead -n%Y%m%d-%H%M%S'

# non-Linux shells sometimes don't support 'which'
# alias which='type -path'

# Cygwin-specific
if [ "$DMAAS_OS" = cygwin ]; then
	cd $HOME
else
	# Everything BUT Cygwin

	# ls colors
	if [ "$DMAAS_OS" != "macosx" ]; then
		eval `dircolors ~/.dir_colors`
	fi

	# Iconify:
	function  ic  { echo -en "\033[2t"; }

	# Restore:
	function  re  { echo -en "\033[1t"; }
	## try:  ic; make a_lot; re


	# magic commands to alter xterm/Terminal.app window titles
	if [ -n "$SSH_TTY" ] || [ -n "$DISPLAY" ]; then # set PROMPT_COMMAND:

	    TAPP="$(hostname | cut -d. -f1)";

	    # on OSX, system PROMPT_COMMAND already shows the working directory, so omit that part
	    if [ "$DMAAS_OS" != "macosx" ]; then
		PROMPT_COMMAND_CWD=":\`dirs +0\`"
	    else
		PROMPT_COMMAND_CWD=""
	    fi

	    PROMPT_COMMAND="echo -ne '\033]0;'$TAPP$PROMPT_COMMAND_CWD'\007';$PROMPT_COMMAND"

	    TPC="$PROMPT_COMMAND"; # original prompt command
	    # 'pp arg' sets title to arg
	    # 'pp' resets title to default
	    function pp
	    {
		if test -z "$1"; then
		    PROMPT_COMMAND=$TPC;
		else
		    unset PROMPT_COMMAND;
		    echo -ne '\033]0;' $@ '\007';
		fi
	    }

	    function xs  ## cd to dir and set title,  'xs .' just puts dirname into title
	    {
		cd $1;  pp ${PWD##*/}
	    }
	fi
	# =========== end xterm window title voodoo
fi

# stupid Debian fucked up xterm's terminfo
#if [ "$DMAAS_OS" = "linux" ]; then
#    export TERM=rxvt
#fi
