# Merge Instructions: Integrating the `bayes_net` Branch

To complete the real-time diagnostic pipeline, you now need to bring in the Bayesian logic that consumes the Kafka topic we've configured. Follow these exact steps.

## Step 1: Review the Differences
Before doing a hard merge, see what is incoming:
```bash
git fetch origin
git diff main origin/bayes_net --stat
```

## Step 2: Perform the Merge
If everything looks good (usually isolated to a new directory like `diagnostic_model/`), merge it into your current environment:
```bash
# Ensure you are on main
git checkout main

# Merge the branch
git merge origin/bayes_net
```
*Note: If there are merge conflicts (likely in `requirements.txt` or `docker-compose.yml`), integrate them carefully. You may need to add `pgmpy` or `networkx` to your local environment if they were only introduced in that branch.*

## Step 3: Start the Pipeline End-to-End
Once merged, start all components:

1. **Start Victim Server, Prometheus, and Kafka via Docker:**
   ```bash
   docker-compose up -d --build
   ```

2. **Start the Bridge:**
   ```bash
   # In a separate terminal
   pip install requests kafka-python
   python bridge.py
   ```

3. **Start the Diagnostic Model (from the merged branch):**
   *(The exact filename depends on your `bayes_net` branch, but usually something like this:)*
   ```bash
   # In a third terminal
   python diagnostic_model/inference.py
   ```

## Step 4: Inject Faults!
Use the FastApi docs (`http://localhost:8000/docs`) to trigger a `/fault/cpu/start` and watch the pipeline automatically detect "Compute_Overload"!
