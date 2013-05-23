Serial-EEG-Reader
=================
Not for inattentive consumption. Work in progress. Seeking accurate time resolution of data coming off Mindwave device.

TODO:
Stream consistent 512 hex codes (bytes) per second. 

Investigate packet dropping ( 0x02 poor signal drops should be renamed to `0x02 signal quality` ).

Document API and remove magic and cruft, especially the coroutine abtruseness.

Refactor, set up unit tests and a convenient virtual env.

Experiment with unadulterated (raw) values from the EEG, rather than the seeming obfuscated values that are
being transformed all sorts of ways; who knows how.

Hot plug a different visualization library. Possible uses are D3.js for a browser, matplot, gnuplot, ad infinitum.

Network the EEG with another computer via a network, if possible. Otherwise a serial port. It would be
very cool to be able to either stream data as an IPC socket straight from the EEG, but since it's an embedded device,
I'd say this is unlikely. More likely, we'll stream from the computer it's hooked up with (Arduino, Rasp Pi, etc.) 
and unfortunately be constrained by the serial port. But we can still network multiple computers through sockets and
stream data realtime through a socket to multiple clients; dream bridge. Node.js and engine.io come to mind.








World Domination.
