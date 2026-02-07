# kpf-test-completions

This directory is used to test completions for kpf.

```
docker run -i -t --rm --name brew-testing \
 --network=host \
 -v $PWD/test-completions/.zshrc:/root/.zshrc \
 -v $PWD/test-completions/.zsh_history:/root/.zsh_history \
 -v $PWD/completions:/root/completions:ro \
 -v $PWD:/root/kpf:ro \
 -v /home/jesse/.minikube:/home/jesse/.minikube \
 -v $HOME/.kube:/root/.kube \
 jgoodier/kpf-test:latest zsh
 ```
