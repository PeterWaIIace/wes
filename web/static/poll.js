export function pollEvery(fn, intervalMs = 10000) {
    let timer = null;
    let inFlight = false;

    async function tick() {
        if (inFlight) return;
        inFlight = true;
        try {
            await fn();
        } finally {
            inFlight = false;
        }
    }

    function start() {
        if (timer) return;
        if (!document.hidden) tick();
        timer = setInterval(() => {
            if (!document.hidden) tick();
        }, intervalMs);
    }

    function stop() {
        if (timer) {
            clearInterval(timer);
            timer = null;
        }
    }

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stop();
        else start();
    });

    start();
    return stop;
}
