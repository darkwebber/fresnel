# Fresnel 0.4.1

This patch moves the downloaded Spark MLX runtime out of Homebrew's versioned
Cellar and into Fresnel's private Application Support directory. The runtime now
survives future `brew upgrade fresnel` operations, while the pinned model and
existing configuration remain untouched.

It retains all 0.4.0 memory, continuation, terminal rendering, clipboard, and
versioned-integration features.
