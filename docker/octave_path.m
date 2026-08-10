radici = {"/usr/share/octave/packages", ...
          "/usr/lib/x86_64-linux-gnu/octave/packages", ...
          "/usr/local/share/octave/packages"};

p = "";

for i = 1:numel(radici)
  r = radici{i};
  if exist(r, "dir") != 7
    continue;
  end
  d = dir(r);
  for k = 1:numel(d)
    if !d(k).isdir
      continue;
    end
    nome = d(k).name;
    if strcmp(nome, ".") || strcmp(nome, "..")
      continue;
    end
    ramo = genpath(fullfile(r, nome));
    if isempty(p)
      p = ramo;
    else
      p = [p pathsep ramo];
    end
  end
end

fid = fopen("/opt/octave_pkg_path", "w");
fputs(fid, p);
fclose(fid);

printf("path pacchetti costruito, %d caratteri\n", numel(p));
