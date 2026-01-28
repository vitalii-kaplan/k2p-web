# k2p-web
K2P-Web: a minimal, web service that converts KNIME workflows to Python/Jupyter. Users upload a sanitized workflow bundle (workflow.knime + per-node settings.xml); a Kubernetes Job runs knime2py in an isolated container and returns results as a ZIP.
