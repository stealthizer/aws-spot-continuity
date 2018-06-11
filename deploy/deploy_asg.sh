#!/bin/bash
if [ "$#" -lt "1" ]
    then printf "Usage: $0 [aws-account]\nExample: $0 dev\n"
else
    profile=$1
    export AWS_PROFILE=$profile
    environment=`echo $profile|cut -d- -f2`
    sceptre update-stack $environment asg
fi
