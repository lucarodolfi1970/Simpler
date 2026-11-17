#!/bin/bash
# the same test without NuGet (Linux, development): csc and the runtime of the SDK
cd "$(dirname "$0")"
R=$(ls -d /usr/lib/dotnet/packs/Microsoft.NETCore.App.Ref/8.*/ref/net8.0 | head -1)
CSC=$(ls /usr/lib/dotnet/sdk/8.*/Roslyn/bincore/csc.dll | head -1)
OUT=${TMPDIR:-/tmp}/updatetest_build; mkdir -p $OUT
refs=""; for f in $R/*.dll; do refs="$refs -r:$f"; done
dotnet $CSC -nologo -noconfig -nullable:enable -out:$OUT/updatetest.dll $refs UpdateTest.cs ../../app/Simpler/UpdateCheck.cs || exit 1
ver=$(ls /usr/lib/dotnet/shared/Microsoft.NETCore.App/ | grep '^8\.' | head -1)
echo "{\"runtimeOptions\":{\"tfm\":\"net8.0\",\"framework\":{\"name\":\"Microsoft.NETCore.App\",\"version\":\"$ver\"}}}" > $OUT/updatetest.runtimeconfig.json
dotnet $OUT/updatetest.dll
