// Export bounded static evidence for an imported executable. Never launches it.
// @category SurveySync.Development
// @menupath
// @toolbar

import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.google.gson.GsonBuilder;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.util.headless.HeadlessScript;
import ghidra.framework.Application;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

public class SurveySyncStaticAudit extends HeadlessScript {
    private boolean isApplicationFunction(Function function) {
        String name = function.getName(true);
        return name.startsWith("main.") || name.startsWith("main::")
            || function.getParentNamespace().getName(true).equals("main");
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) {
            throw new IllegalArgumentException("Expected one argument: output JSON path");
        }
        Path output = Path.of(args[0]).toAbsolutePath();
        Files.createDirectories(output.getParent());
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("schema_version", 1);
        report.put("method", "Ghidra headless import, static auto-analysis, bounded decompilation");
        report.put("ghidra_version", Application.getApplicationVersion());
        report.put("program_name", currentProgram.getName());
        report.put("executable_sha256", currentProgram.getExecutableSHA256());
        report.put("executable_format", currentProgram.getExecutableFormat());
        report.put("language", currentProgram.getLanguageID().toString());
        report.put("compiler", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        report.put("image_base", currentProgram.getImageBase().toString());
        report.put("pointer_size", currentProgram.getDefaultPointerSize());
        report.put("analysis_timeout_occurred", analysisTimeoutOccurred());
        report.put("limitations", Arrays.asList(
            "The target executable is never run by this script.",
            "Static imports and decompiler output do not establish complete runtime behavior.",
            "Recovered names, types, and pseudocode are analysis results, not original source.",
            "This report is not an antivirus verdict or release clearance."
        ));

        List<Map<String, Object>> sections = new ArrayList<>();
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            Map<String, Object> section = new LinkedHashMap<>();
            section.put("name", block.getName());
            section.put("start", block.getStart().toString());
            section.put("size", block.getSize());
            section.put("read", block.isRead());
            section.put("write", block.isWrite());
            section.put("execute", block.isExecute());
            section.put("initialized", block.isInitialized());
            sections.add(section);
        }
        report.put("memory_blocks", sections);
        String[] libraries = currentProgram.getExternalManager().getExternalLibraryNames();
        Arrays.sort(libraries);
        report.put("external_libraries", libraries);

        List<Map<String, Object>> externals = new ArrayList<>();
        SymbolIterator symbols = currentProgram.getSymbolTable().getExternalSymbols();
        while (symbols.hasNext()) {
            monitor.checkCancelled();
            Symbol symbol = symbols.next();
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", symbol.getName(true));
            item.put("type", symbol.getSymbolType().toString());
            item.put("address", symbol.getAddress().toString());
            externals.add(item);
        }
        externals.sort(Comparator.comparing(item -> item.get("name").toString()));
        report.put("external_symbols", externals);

        List<Function> mainFunctions = new ArrayList<>();
        int total = 0;
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext()) {
            monitor.checkCancelled();
            Function function = functions.next();
            total++;
            if (isApplicationFunction(function)) {
                mainFunctions.add(function);
            }
        }
        report.put("function_count", total);
        report.put("application_function_count", mainFunctions.size());
        report.put("application_function_rule", "Recovered function or namespace begins with main");
        mainFunctions.sort(Comparator.comparing(function -> function.getEntryPoint().toString()));

        List<Map<String, Object>> application = new ArrayList<>();
        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                throw new IllegalStateException("Decompiler could not open imported program");
            }
            int decompiled = 0;
            for (Function function : mainFunctions) {
                monitor.checkCancelled();
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("name", function.getName(true));
                item.put("entry", function.getEntryPoint().toString());
                item.put("signature", function.getSignature().toString());
                item.put("body_bytes", function.getBody().getNumAddresses());
                List<String> calls = new ArrayList<>();
                for (Function callee : function.getCalledFunctions(monitor)) {
                    calls.add(callee.getName(true));
                }
                calls.sort(String::compareTo);
                item.put("direct_calls", calls);
                if (decompiled < 48) {
                    DecompileResults result = decompiler.decompileFunction(function, 20, monitor);
                    item.put("decompilation_completed", result.decompileCompleted());
                    item.put("decompilation_message", result.getErrorMessage());
                    if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
                        String filename = function.getEntryPoint().toString() + "_"
                            + function.getName().replaceAll("[^A-Za-z0-9_.-]", "_") + ".c";
                        Path listing = output.getParent().resolve("decompiled").resolve(filename);
                        Files.createDirectories(listing.getParent());
                        Files.writeString(listing, result.getDecompiledFunction().getC(), StandardCharsets.UTF_8);
                        item.put("pseudocode_file", "decompiled/" + filename);
                    }
                    decompiled++;
                } else {
                    item.put("decompilation_completed", false);
                    item.put("decompilation_message", "Bound of 48 application functions reached");
                }
                application.add(item);
            }
        } finally {
            decompiler.dispose();
        }
        report.put("application_functions", application);
        try (BufferedWriter writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(report, writer);
            writer.newLine();
        }
        println("SurveySync static report: " + output);
        println("Recovered " + total + " functions; " + mainFunctions.size() + " main-package functions.");
    }
}
