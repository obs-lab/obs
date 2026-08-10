FROM gnuoctave/octave:9.2.0

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        octave-statistics \
        octave-io \
    && rm -rf /var/lib/apt/lists/*

COPY octave_path.m /opt/octave_path.m

RUN cd /opt && octave --no-gui --quiet octave_path.m \
    && test -s /opt/octave_pkg_path \
    && chmod a+r /opt/octave_pkg_path

RUN printf '#!/bin/sh\nOCTAVE_PATH="$(cat /opt/octave_pkg_path)"\nexport OCTAVE_PATH\nexec /usr/bin/octave "$@"\n' \
      > /usr/local/bin/octave \
    && chmod a+rx /usr/local/bin/octave

ENV GNUTERM=dumb

RUN octave --no-gui --quiet --eval \
      "if exist('ismissing') == 0, error('statistics non nel path'); end; \
       disp('Octave pronto: pacchetto statistics caricato');"
