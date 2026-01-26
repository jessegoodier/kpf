docker run -d --name kpf-testing --user 0 \
    --network=host \
    -e KUBECONFIG=/toolbox/kube/config:ro \
    -v $PWD:/toolbox/kpf:ro \
    -v ./temp:/toolbox/kube:ro \
    -v $HOME/.aws:/home/toolbox/.aws:ro \
    --entrypoint sleep \
    ghcr.io/jessegoodier/toolbox:latest infinity
